<html>
<head>
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

</style>
</head>
<body>
<div class="row">
  <div class="column">
    <h1>Meal Plan</h1>
    % if mealplan:
      <h2>{{mealplan.name}}</h2>
      % for meal_index, meal in enumerate(mealplan.meals):
        <h3>{{meal.name}} <a class="x" href="/delete-meal/{{meal_index}}"> &#9447;</a></h3>
        <ul>
        % for recipe_index, recipe in enumerate(meal.recipes):
          <li>{{recipe.name}} <a class="x" href="/delete-recipe-from-meal/{{meal_index}}/{{recipe_index}}"> &#9447;</a></li>
        % end
        <li><form action="/add-recipe" method="POST">
            <input list="recipelist" name="recipe" method="POST">
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
      <input type="text" id="meal" name="meal">
      <input type="submit" value="Add Meal"></form>
    % end 

  </div>

  <div class="column">
  <h1>Shopping List</h1>
% if need:
  <h2>To Get</h2>
  <table style="width:100%">
  % for item in need:
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
     <td style="width:20%"><a href="/got/{{item.id}}">☐</a></td>
     <td style="width:20%;opacity:0.5" ><a href="/have/{{item.id}}">Already&nbsp;have&nbsp;it!</a></td>
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
