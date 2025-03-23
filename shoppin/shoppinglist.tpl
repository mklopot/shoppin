<html>
<head>

    <script>
        document.addEventListener("DOMContentLoaded", function(event) { 
            var scrollpos = localStorage.getItem('scrollpos');
            if (scrollpos) window.scrollTo(0, scrollpos);
        });

        window.onbeforeunload = function(e) {
            localStorage.setItem('scrollpos', window.scrollY);
        };
    </script>

<style>
a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

</style>
</head>
<body>
<div class="row">
  <div class="column">
    <h1>Meal Plan</h1>
    % if mealplan:
      <h2>{{mealplan.name}}</h2>
      % for meal_index, meal in enumerate(mealplan.meals):
        <h3><span class="greendot">{{!"&#128994;" if meal in meals_ready_to_cook else ""}}</span> {{meal.name}} <a class="x" href="/delete-meal/{{meal_index}}"> &#9447;</a></h3>
        <ul>
        % for recipe_index, recipe in enumerate(meal.recipes):
          <li><span class="greendot">{{!"&#128994;" if recipe in recipes_ready_to_cook else ""}}</span> {{recipe.name}} <a class="x" href="/delete-recipe-from-meal/{{meal_index}}/{{recipe_index}}"> &#9447;</a></li>
        % end
        <li><form action="/add-recipe" method="POST">
            <input list="recipelist" name="recipe" method="POST" required>
            <input type="hidden" name="meal_index" value={{meal_index}}>
            <input type="submit" value="Add Recipe">
            <datalist id="recipelist">
            % for recipename in recipelist:
            <option value="{{recipename}}">
            % end
            </datalist>
            </form>
        </li>
        </ul>
      % end
      <form action="/add-meal" method="POST">
      <!--label for="meal"><h3>Add meal:</h3></label-->
      % if mealplan.meals:
      <input type="text" id="meal" name="meal">
      % else:
      <input type="text" id="meal" name="meal" value="Taco Tuesday Dinner" required>
      % end
      <input type="submit" value="Add Meal"></form>
    % end 

  </div>

  <div class="column">
  <h1>Shopping List</h1>

    <div>
    <h2>Add Item</h2>
    <form action="/add-item" method="POST">
    <input type="text" id="name" name="name" method="POST" required>
    <label for="name">Name</label><br>

    <input type="text" id="amount" name="amount" value="1" method="POST">
    <label for="amount">Amount</label><br>

    <input type="text" id="brand" name="brand" method="POST">
    <label for="brand">Brand <i>optional</i></label><br>

    <input type="text" id="vendor" name="vendor" method="POST">
    <label for="vendor">Best Vendor <i>optional</i></label><br>

    <input type="submit" value="Add Item"><br>
    </form>
    </div>
% if need:
  <h2>To Get</h2>
  <table style="width:100%">
  % for item in need:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{(', '.join([ingredient.attribution.name for ingredient in item.ingredients]) if item.ingredients else "one-time purchase")}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     % if item.locked:
     <td style="width:20%"><a href="/got/{{item.id}}">☐</a></td>
     % else:
     <td style="width:20%"><a href="/got/{{item.id}}">☐</a></td>
     <td style="width:20%;opacity:0.5" ><a style="border:1px solid blue" href="/have/{{item.id}}">Already&nbsp;have&nbsp;it!</a></td>
     <td style="width:5%"><a href="/lock/{{item.id}}">&empty;</a></td>
     % end
  </tr>
  % end
</table>
% end

% if got:
  <h2>Got</h2>
  <table style="width:100%">
  % for item in got:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{', '.join([ingredient.attribution.name for ingredient in item.ingredients])}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:20%">&#x2705;</td>
     <td style="width:20%;opacity:0.5"><a href="/need/{{item.id}}">Need it!</a></td>
  </tr>
  % end
</table>
% end

% if have:
  <h2>Already Have</h2>
  <table style="width:100%">
  % for item in have:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{', '.join([ingredient.attribution.name for ingredient in item.ingredients])}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:20%;opacity:0.5"><a href="/need/{{item.id}}">Need it!</a></td>
  </tr>
  % end
</table>
% end

</div>
</div>
</body>
</html>
