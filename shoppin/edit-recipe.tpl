<html>
<head>
    <meta http-equiv="refresh" content="1200">
     <script>
         document.addEventListener("DOMContentLoaded", function(event) {
             var scrollpos = localStorage.getItem('scrollpos' + '-' + window.location.href);
             if (scrollpos) window.scrollTo(0, scrollpos);
         });
 
         window.onbeforeunload = function(e) {
             localStorage.setItem('scrollpos'+ '-' + window.location.href, window.scrollY);
         };
     </script>
    <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.5/dist/htmx.min.js" integrity="sha384-t4DxZSyQK+0Uv4jzy5B0QyHyWQD2GFURUmxKMBVww9+e2EJ0ei/vCvv7+79z0fkr" crossorigin="anonymous"></script>

<style>
p{
  width: 50%;
}

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

.alreadyhave{
  text-align: center;
}

</style>
</head>
  <body>
    <h1><a href="/recipe/{{backbutton}}">&larr;</a> <span style="color:red">Editing </span>{{recipe.name}}</h1>

    <form hx-post="/save-recipe" hx-trigger="change" hx-swap="none">
    <input type="hidden" name="recipe" value="{{recipe.name}}">

    <label for="description"><h2>Description</h2></label>
    <textarea name="description" id="description" rows="5" cols="80">{{recipe.description}}</textarea>

    <label for="directions"><h2>Directions</h2></label>
    <textarea name="directions" id="directions" rows="12" cols="80">{{recipe.directions}}</textarea>
    </form>

    <h2>Ingredients</h2>
      <ul>
      % for ingredient_index, item in enumerate(recipe.ingredients):
        <li>{{item.name}} 
         &nbsp;&nbsp;{{f"{item.amount:.2g}"}} {{item.amount_unit}}
        % if item.optional:
         &nbsp;&nbsp;<span class="optional">optional</span>
        % end
        % if item.brand:
         &nbsp;&nbsp;Brand: {{item.brand}}
        % end
        % if item.vendor:
         &nbsp;&nbsp;Best Vendor: {{item.vendor}}
        % end
         <a class="x" href="/delete-ingredient/{{backbutton}}/{{recipe.name}}/{{ingredient_index}}"> &#9447;</a>
      % end
      </ul>
      <h3>Add Ingredient</h3>
        <form action="/add-ingredient" method="POST">
          <input type="checkbox" id="optional" name="optional" size="30" method="POST">
          <label for="optional">Optional</label><br>

          <input type="text" id="name" name="name" method="POST" size="30" placeholder='Name of ingredient, like "celery"' required>
          <label for="name">Name</label><br>

          <input type="text" id="amount" name="amount" value="1" size="30" method="POST">
          <label for="amount">Amount</label><br>

          <input type="text" id="brand" name="brand" size="30" method="POST">
          <label for="brand">Brand <i>optional</i></label><br>

          <input type="text" id="vendor" name="vendor" size="30" method="POST">
          <label for="vendor">Best Vendor (King Soopers, Safeway, etc) <i>optional</i></label><br>

          <input type="hidden" name="recipe" value="{{recipe.name}}">
          <input type="hidden" name="recipe_id" value="{{backbutton}}">
          <input type="submit" value="+ Add Ingredient" hx-boost="true" hx-swap='innerHTML show:no-scroll'><br>
        </form>
  </body>
</html>
